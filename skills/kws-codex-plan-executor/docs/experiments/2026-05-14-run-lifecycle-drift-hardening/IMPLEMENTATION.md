# Run Lifecycle And Drift-Aware Reporter Implementation Details

This document expands `PLAN.md` into concrete implementation guidance. It is
written for a future implementation pass against `kws-codex-plan-executor`; it
does not claim the changes are already applied.

## Corrected Principle

Do not treat `meta.pid` as executor-session liveness.

`append_learning_event.py init-run` writes process metadata while a short-lived
helper process is running. That helper exits immediately after writing
`meta.json` and `index.jsonl`. A dead helper pid is expected and should not
make a run stale.

The reporter should instead answer:

1. Did the run write a terminal `final.json`?
2. If not, does the project-local state show active progress or pending finalization?
3. If project state is unavailable, is the worktree missing or unreadable?
4. If state exists but is old and inactive, is this a stale candidate?

## Implementation Order

1. Add failing eval fixtures for the corrected PromptGate case.
2. Add project-state loading and summarization to the health reporter.
3. Change classification precedence to prefer `final.json`, then project state.
4. Replace hard `dead_pid_unclosed` stale classification with `helper_pid_dead` informational metadata and `stale_candidate` state-based classification.
5. Add git drift summary.
6. Tighten docs and terminal-state context health validation.
7. Run package verification and update `docs/verification-log.md`.

## Task 1: Add Failing Reporter Fixtures

**Files:**
- Modify: `evals/check_learning_log.py`

### Step 1.1: Add Project State Fixture Helper

Add this helper near the existing fixture builders:

```python
def write_project_state(worktree: Path, run_id: str, *, state: dict) -> Path:
    state_path = worktree / ".codex-orchestrator" / "runs" / run_id / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return state_path
```

Add a reusable state builder:

```python
def base_project_state(run_id: str, *, current_task: str, lifecycle_outcome: str | None = None) -> dict:
    return {
        "schema_version": "1",
        "run_id": run_id,
        "mode": "interactive",
        "workspace": "/tmp/worktree",
        "plan": "/tmp/worktree/docs/superpowers/plans/example.md",
        "branch": "codex/example",
        "worktree": "/tmp/worktree",
        "run_dir": f".codex-orchestrator/runs/{run_id}",
        "state_path": f".codex-orchestrator/runs/{run_id}/state.json",
        "context_snapshot_path": f".codex-orchestrator/runs/{run_id}/context.json",
        "context_basis_hash": "abc123",
        "context_health": {
            "status": "yellow",
            "last_checked_at": "2026-05-14T14:47:46Z",
            "context_snapshot_present": True,
            "context_basis_hash_recorded": True,
            "active_task_contract_present": True,
            "next_action": "Run final acceptance verification commands.",
            "open_questions": [],
            "known_assumptions": [],
            "handoff_ready": True,
        },
        "current_task": current_task,
        "current_phase": "task_loop",
        "lifecycle_outcome": lifecycle_outcome,
        "handoff_reason": "",
        "tasks": {
            "task_1": {"status": "completed", "risk": "low", "files_declared": [], "contract": {}, "review_retries": 0, "verifier_retries": 0},
            "task_2": {"status": "completed", "risk": "low", "files_declared": [], "contract": {}, "review_retries": 0, "verifier_retries": 0},
            "task_7": {"status": "pending", "risk": "mid", "files_declared": [], "contract": {}, "review_retries": 0, "verifier_retries": 0},
        },
        "timestamps": {
            "started_at": "2026-05-14T14:47:46Z",
            "updated_at": "2026-05-14T15:01:03Z",
            "completed_at": None,
        },
    }
```

Keep this helper test-local. It does not need to satisfy every production
state validation rule because the reporter must tolerate partial in-progress
state.

### Step 1.2: Create Active State With Dead Helper PID

Build a run fixture where:

- `meta.pid` is an impossible dead pid.
- `final.json` is absent.
- `meta.worktree_path` points at a temp worktree.
- `state.json` shows `current_phase=task_loop`, `current_task=task_7`, Tasks 1-2 completed, Task 7 pending.

Expected:

```json
{
  "status": "needs_finalization",
  "diagnostics": {
    "info": ["helper_pid_dead", "missing_learning_final"],
    "warnings": []
  }
}
```

If the classification chooses `in_progress` instead of `needs_finalization`
because pending implementation tasks remain, update the fixture to make all
implementation tasks completed and only final verification pending.

### Step 1.3: Create Stale Candidate Fixture

Build a run fixture where:

- `final.json` is absent.
- project state exists.
- all task statuses are `pending` or one task is `in_progress`.
- `timestamps.updated_at` is older than the stale threshold.
- git status is clean.

Expected:

```json
{
  "status": "stale_candidate",
  "diagnostics": {
    "warnings": ["project_state_inactive_past_threshold"]
  }
}
```

### Step 1.4: Create Missing Worktree Fixture

Build a run fixture where:

- `meta.worktree_path` points to a path that does not exist.
- `final.json` is absent.

Expected:

```json
{
  "status": "unknown",
  "diagnostics": {
    "warnings": ["missing_worktree", "missing_project_state"]
  }
}
```

### Step 1.5: Run The Eval

Run:

```bash
python3 evals/check_learning_log.py
```

Expected before implementation:

```text
passed=false
```

The failure should be on the new project-aware classifications, not on existing
learning-log validation.

## Task 2: Add Project State Loading

**Files:**
- Modify: `scripts/check_learning_log_health.py`

### Step 2.1: Resolve Worktree And State Path

Add helpers:

```python
def resolve_worktree_path(meta: dict[str, Any]) -> Path | None:
    value = meta.get("worktree_path")
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value).expanduser()


def resolve_project_state_path(meta: dict[str, Any]) -> Path | None:
    worktree = resolve_worktree_path(meta)
    state_path = meta.get("state_path")
    if worktree is None or not isinstance(state_path, str) or not state_path.strip():
        return None
    candidate = Path(state_path)
    if candidate.is_absolute():
        return candidate
    return worktree / candidate
```

### Step 2.2: Read State Tolerantly

Add:

```python
def read_project_state(meta: dict[str, Any]) -> tuple[Path | None, dict[str, Any] | None, list[str]]:
    diagnostics: list[str] = []
    worktree = resolve_worktree_path(meta)
    if worktree is None:
        diagnostics.append("missing_worktree_path")
        return None, None, diagnostics
    if not worktree.exists():
        diagnostics.append("missing_worktree")
    state_path = resolve_project_state_path(meta)
    if state_path is None:
        diagnostics.append("missing_state_path")
        return None, None, diagnostics
    state = read_json(state_path)
    if state is None:
        diagnostics.append("missing_project_state")
        return state_path, None, diagnostics
    return state_path, state, diagnostics
```

Do not raise for missing state. Health reporting must remain read-only and
best-effort.

### Step 2.3: Summarize State

Add:

```python
def task_counts(state: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        return counts
    for task in tasks.values():
        if not isinstance(task, dict):
            continue
        status = str(task.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def summarize_project_state(state_path: Path, state: dict[str, Any]) -> dict[str, Any]:
    health = state.get("context_health") if isinstance(state.get("context_health"), dict) else {}
    return {
        "state_path": str(state_path),
        "current_task": state.get("current_task"),
        "current_phase": state.get("current_phase"),
        "lifecycle_outcome": state.get("lifecycle_outcome"),
        "context_health_status": health.get("status"),
        "context_health_last_checked_at": health.get("last_checked_at"),
        "next_action": health.get("next_action"),
        "task_counts": task_counts(state),
        "timestamps": state.get("timestamps") if isinstance(state.get("timestamps"), dict) else {},
    }
```

## Task 3: Classify By Final Then Project State

**Files:**
- Modify: `scripts/check_learning_log_health.py`

### Step 3.1: Add Diagnostics Shape

Replace the single `warnings` list with:

```python
diagnostics = {"info": [], "warnings": []}
```

For backwards compatibility, keep `warnings` in the returned JSON for one
release cycle by setting it to `diagnostics["warnings"]`.

### Step 3.2: Implement Project-State Classifier

Add:

```python
def classify_from_project_state(state: dict[str, Any], *, now: dt.datetime, stale_after_minutes: int) -> tuple[str, list[str]]:
    warnings: list[str] = []
    outcome = state.get("lifecycle_outcome")
    if outcome == "finished":
        return "needs_learning_final", ["missing_learning_final"]
    if outcome in {"blocked", "failed", "userinterlude", "askuserQuestion"}:
        return str(outcome), ["missing_learning_final"]

    counts = task_counts(state)
    if counts.get("in_progress", 0) > 0:
        return "in_progress", []

    current_phase = state.get("current_phase")
    if current_phase == "task_loop":
        pending = counts.get("pending", 0)
        completed = counts.get("completed", 0)
        if pending > 0 and completed > 0:
            return "in_progress", []
        if pending > 0:
            stale_warning = stale_warning_from_state_age(state, now=now, stale_after_minutes=stale_after_minutes)
            if stale_warning:
                return "stale_candidate", [stale_warning]
            return "in_progress", []

    stale_warning = stale_warning_from_state_age(state, now=now, stale_after_minutes=stale_after_minutes)
    if stale_warning:
        return "stale_candidate", [stale_warning]
    return "unknown", warnings
```

Add:

```python
def stale_warning_from_state_age(state: dict[str, Any], *, now: dt.datetime, stale_after_minutes: int) -> str | None:
    timestamps = state.get("timestamps") if isinstance(state.get("timestamps"), dict) else {}
    updated_at = parse_time(timestamps.get("updated_at") if isinstance(timestamps.get("updated_at"), str) else None)
    if updated_at is None:
        return None
    if now - updated_at > dt.timedelta(minutes=stale_after_minutes):
        return "project_state_inactive_past_threshold"
    return None
```

### Step 3.3: Update `summarize_run`

Use this precedence:

```python
if final and final.get("outcome"):
    status = str(final["outcome"])
elif project_state is not None:
    status, state_warnings = classify_from_project_state(project_state, now=now, stale_after_minutes=stale_after_minutes)
else:
    status = "unknown"
```

When `final` is absent and `project_state` exists, append `missing_learning_final`
to `diagnostics.info`, not `warnings`, unless the project state itself is
terminal and should have been closed.

If `pid_is_alive(meta.get("pid")) is False`, append `helper_pid_dead` to
`diagnostics.info`. Do not use it as a stale condition.

## Task 4: Add Git Drift Summary

**Files:**
- Modify: `scripts/check_learning_log_health.py`

### Step 4.1: Add Subprocess Import

Add:

```python
import subprocess
```

### Step 4.2: Implement Git Summary

Add:

```python
def summarize_git_state(worktree: Path | None) -> dict[str, Any] | None:
    if worktree is None or not worktree.exists():
        return None
    try:
        status = subprocess.run(
            ["git", "-C", str(worktree), "status", "--short", "--untracked-files=all"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
        head = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "--short", "HEAD"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
        branch = subprocess.run(
            ["git", "-C", str(worktree), "branch", "--show-current"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"worktree_exists": True, "git_readable": False}

    lines = [line for line in status.stdout.splitlines() if line.strip()] if status.returncode == 0 else []
    return {
        "worktree_exists": True,
        "git_readable": status.returncode == 0,
        "short_status_count": len(lines),
        "untracked_count": sum(1 for line in lines if line.startswith("??")),
        "head": head.stdout.strip() if head.returncode == 0 else None,
        "branch": branch.stdout.strip() if branch.returncode == 0 else None,
    }
```

### Step 4.3: Emit Drift Diagnostics

If `status in {"in_progress", "needs_finalization"}` and
`git_state.short_status_count > 0`, add:

```text
dirty_worktree_during_in_progress
```

This is a warning, not a failure. Active work often has dirty files, but the
report should make that explicit.

## Task 5: Fix Context Health Timestamp Discipline

**Files:**
- Modify: `references/execution-cycle.md`
- Modify: `references/state-schema.md`
- Modify: `scripts/validate_state.py`
- Modify: `evals/check_state_schema.py`

### Step 5.1: Add Documentation Rule

Add to `references/execution-cycle.md` near context-health refresh:

```markdown
Whenever any `context_health` field changes, update
`context_health.last_checked_at` in the same state write. A stale timestamp is
misleading during resume because `next_action` can look fresh while the health
check date still points at an earlier task.
```

### Step 5.2: Add Terminal Validation

In `validate_state.py`, add a timestamp parser and terminal check:

```python
from datetime import datetime


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
```

Inside `_validate_context_health`, when `outcome == "finished"`:

```python
updated_at = _parse_ts((data.get("timestamps") or {}).get("updated_at") if isinstance(data.get("timestamps"), dict) else None)
checked_at = _parse_ts(health.get("last_checked_at"))
if updated_at is not None and checked_at is not None and checked_at < updated_at:
    errors.append("context_health.last_checked_at must not be older than timestamps.updated_at when lifecycle_outcome is finished")
```

Do not make this a hard error for non-terminal runs.

## Task 6: Update Documentation

**Files:**
- Modify: `references/learning-log.md`
- Modify: `docs/state-and-logging.md`
- Modify: `docs/evals-and-verification.md`
- Modify: `docs/risks-limitations-deferrals.md`
- Modify: `docs/verification-log.md`

### Required Wording

Add this concept to `references/learning-log.md`:

```markdown
`meta.helper_pid` and legacy `meta.pid` identify the helper process that wrote
the learning-log metadata. They do not identify a durable Codex execution
session. Health reporters must not classify a run as stale from helper-pid
liveness alone.
```

Add this precedence to `docs/state-and-logging.md`:

```markdown
Run health is resolved in this order: terminal `final.json`, project-local
state, then learning-log metadata. Missing `final.json` is normal while a
project-local state file shows active task-loop progress.
```

## Expected JSON Output

For the corrected PromptGate case, `check_learning_log_health.py --latest 1 --json`
should produce a shape like:

```json
{
  "schema_version": "1",
  "runs": [
    {
      "run_id": "20260514T144709Z-promptgate-codex-promptgate-adapter-runtime-integra-02d03510e465-e22f38",
      "status": "in_progress",
      "event_count": 0,
      "diagnostics": {
        "info": ["helper_pid_dead", "missing_learning_final"],
        "warnings": []
      },
      "project_state": {
        "current_task": "task_7",
        "current_phase": "task_loop",
        "lifecycle_outcome": null,
        "context_health_status": "yellow",
        "task_counts": {
          "completed": 6,
          "pending": 1
        }
      },
      "git_state": {
        "worktree_exists": true,
        "short_status_count": 0,
        "untracked_count": 0
      },
      "warnings": []
    }
  ]
}
```

## Verification Commands

Run:

```bash
python3 evals/check_learning_log.py
python3 evals/check_state_schema.py
python3 evals/check_skill_contract.py --skill SKILL.md
python3 scripts/check_learning_log_health.py --latest 5 --json
python3 /Users/kws/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
git diff --check -- skills/kws-codex-plan-executor
graphify update .
```

Expected:

- learning-log eval passes all legacy and project-aware fixtures.
- state schema eval passes, including terminal timestamp freshness.
- skill contract remains valid.
- health reporter does not mark the PromptGate adapter-runtime run stale while its project state shows active progress or pending finalization.

## Rollout Notes

- Keep legacy `warnings` for compatibility but introduce `diagnostics.info`.
- Do not delete legacy `pid` immediately; emit `helper_pid` and read both.
- Avoid version bump until the actual behavior change is implemented. These experiment docs alone are planning artifacts.
- When implementation ships, update `HISTORY.md`, `ARCHITECTURE.md`, `README.md`, and `SKILL.md` only if the runtime contract or public behavior changes.
