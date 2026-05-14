# Run Lifecycle And Drift-Aware Reporter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `kws-codex-plan-executor` health reporting distinguish active in-progress runs from genuinely stale runs, and surface state/file drift without false alarms.

**Architecture:** Keep the existing file-based learning log, but treat it as a run index and terminal-event store rather than the only health source. Add project-state-aware reporting that reads `meta.worktree_path`, resolves `.codex-orchestrator/runs/<run_id>/state.json`, classifies lifecycle from project state first, and uses learning-log data only to explain terminal or missing-terminal conditions.

**Tech Stack:** Python 3 standard library, JSON/JSONL, git CLI status inspection, existing `scripts/check_learning_log_health.py`, `scripts/append_learning_event.py`, `evals/check_learning_log.py`, `.codex-orchestrator/runs/<run_id>/state.json`.

---

## Source Basis

This plan corrects the analysis of the latest run:

```text
20260514T144709Z-promptgate-codex-promptgate-adapter-runtime-integra-02d03510e465-e22f38
```

Initial interpretation said:

- learning log status was `unknown`
- `final.json` was missing
- `pid=71251` was not alive
- Task 2 appeared to have file/state drift

Follow-up verification showed:

- `meta.pid` is the short-lived `append_learning_event.py init-run` helper pid, not the long-lived Codex executor session.
- The project-local state had advanced to Task 7, with Tasks 1-6 completed.
- Task 2 RED/GREEN evidence was present in state.
- The worktree was clean after later commits.
- Missing `final.json` was expected while final verification had not completed.

The actual problem is not an abandoned run. The problem is that the reporter can over-read learning-log metadata and under-read project-local state, creating a false stale or false drift diagnosis.

## Problems To Solve

1. `meta.pid` is ambiguous. It currently records the helper process pid from `append_learning_event.py`, not a durable executor pid.
2. `check_learning_log_health.py` reports `unknown` when `final.json` is absent, even when project state clearly shows active task-loop progress.
3. Stale detection uses helper pid liveness, which can falsely classify active or recently active runs as dead.
4. Project-local state timestamps can be internally stale: `context_health.next_action` may advance while `context_health.last_checked_at` remains old.
5. State/file drift needs to be reported against committed and uncommitted git state, not inferred from one snapshot during an active run.
6. `index_outcome_stale` is noisy for append-only `index.jsonl`; it should be informational when `final.json` gives a terminal outcome.

## Non-Goals

- Do not introduce a daemon or background heartbeat service.
- Do not try to identify the live Codex desktop process.
- Do not mutate learning logs from the health reporter.
- Do not make `final.json` required before a run is actually complete.
- Do not treat a clean worktree with pending final verification as failed.
- Do not auto-close unknown runs from reporting code.

## File Map

| File | Responsibility |
| --- | --- |
| `scripts/append_learning_event.py` | Rename or document `pid` as helper-process metadata; optionally emit `helper_pid` while retaining `pid` for compatibility. |
| `scripts/check_learning_log_health.py` | Resolve project state from `meta.worktree_path` and classify active, terminal, stale-candidate, and unknown runs. |
| `evals/check_learning_log.py` | Add fixtures for active project state with dead helper pid, stale project state, missing worktree, and append-only index warnings. |
| `references/learning-log.md` | Clarify that helper pid is not executor liveness and that `final.json` absence is normal for in-progress runs. |
| `references/state-schema.md` | Add optional reporter fields or docs for `timestamps.updated_at`, active task status, and drift summaries if persisted. |
| `references/execution-cycle.md` | Require `context_health.last_checked_at` updates whenever `context_health` changes. |
| `docs/state-and-logging.md` | Explain source precedence: terminal `final.json`, then project state, then learning-log metadata. |
| `docs/evals-and-verification.md` | Document the new health reporter fixtures and expected classifications. |
| `docs/risks-limitations-deferrals.md` | Record that active-session liveness is inferred from state, not guaranteed by process lookup. |
| `docs/verification-log.md` | Record implementation verification evidence. |

## Classification Model

The health reporter should classify each run with this precedence:

1. `final.json.outcome` exists:
   - `success`, `blocked`, or `error`
   - `index_outcome_stale` becomes `info`, not warning, when index differs.
2. Project-local state exists and has no terminal `lifecycle_outcome`:
   - `in_progress` when any task is `in_progress`, or when `current_phase` is `task_loop` and pending tasks remain.
   - `needs_finalization` when all implementation tasks are completed but final verification or `completion_audit` is pending.
3. Project-local state exists with non-success terminal outcome:
   - `blocked`, `failed`, `userinterlude`, or `askuserQuestion` as reported by state, while learning `final.json` remains missing.
   - Add `missing_learning_final` diagnostic.
4. Project-local state is absent or unreadable:
   - `unknown` unless the worktree is missing or stale thresholds are crossed.
5. Stale candidate:
   - only when no `final.json`, no recent project-state update, no active task progress, and the worktree state has not changed recently enough to explain the run.
   - helper pid liveness alone must never classify a run as stale.

Recommended public statuses:

```text
success
blocked
error
failed
in_progress
needs_finalization
stale_candidate
unknown
```

## State/Drift Model

The reporter should return a compact `project_state` object when available:

```json
{
  "project_state": {
    "state_path": "/abs/worktree/.codex-orchestrator/runs/<run_id>/state.json",
    "current_task": "task_7",
    "current_phase": "task_loop",
    "lifecycle_outcome": null,
    "context_health_status": "yellow",
    "context_health_last_checked_at": "2026-05-14T14:47:46Z",
    "next_action": "Run final acceptance verification commands.",
    "task_counts": {
      "completed": 6,
      "pending": 1,
      "in_progress": 0,
      "blocked": 0,
      "error": 0
    }
  }
}
```

The reporter should return a compact `git_state` object when `worktree_path` exists:

```json
{
  "git_state": {
    "worktree_exists": true,
    "short_status_count": 0,
    "untracked_count": 0,
    "head": "f11031b",
    "branch": "codex/promptgate-adapter-runtime-integration"
  }
}
```

Drift warnings should be specific:

- `state_ahead_of_learning_final`: state shows active or terminal progress but learning `final.json` is absent.
- `context_health_timestamp_stale`: `context_health.last_checked_at` is older than `timestamps.updated_at`.
- `dirty_worktree_during_in_progress`: uncommitted changes exist while state is active.
- `untracked_task_files`: untracked files match declared files for the active task.
- `missing_project_state`: state path cannot be read.
- `missing_worktree`: `meta.worktree_path` no longer exists.

## Milestones

### Milestone 1: Rename Helper PID Semantics

Acceptance:

- New `init-run` metadata writes `helper_pid`.
- Existing `pid` remains accepted for backwards compatibility.
- Docs state that neither field proves executor-session liveness.
- Health reporter no longer uses helper pid as the primary stale signal.

### Milestone 2: Add Project-State-Aware Health Classification

Acceptance:

- Reporter reads `meta.worktree_path` and `meta.state_path`.
- Reporter resolves relative state paths inside the worktree.
- In-progress project state overrides absent `final.json`.
- The PromptGate adapter-runtime case classifies as `in_progress` or `needs_finalization`, not stale.

### Milestone 3: Add Drift Diagnostics

Acceptance:

- Reporter includes `project_state` summary when readable.
- Reporter includes `git_state` summary when the worktree exists.
- Reporter emits warning codes only for actionable mismatches.
- Append-only index mismatch is demoted to informational diagnostics.

### Milestone 4: Improve State Timestamp Discipline

Acceptance:

- Execution docs require updating `context_health.last_checked_at` whenever `context_health` fields change.
- State validation warns or fails when `context_health.last_checked_at` is older than `timestamps.updated_at` for terminal `finished` state.
- The rule does not block active runs solely because old state exists.

### Milestone 5: Add Deterministic Evals

Acceptance:

- `evals/check_learning_log.py` covers active project state with dead helper pid.
- It covers stale candidate caused by old project state and missing final.
- It covers missing worktree.
- It covers terminal `final.json` with append-only index mismatch as info.

## Task Plan

### Task 1: Add Reporter Fixtures For Project State

**Files:**
- Modify: `evals/check_learning_log.py`

- [ ] Add a helper that creates a temporary worktree-like directory with `.codex-orchestrator/runs/<run_id>/state.json`.
- [ ] Add `active_project_state_dead_helper_pid` fixture.
- [ ] Add `needs_finalization_project_state` fixture.
- [ ] Add `old_project_state_stale_candidate` fixture.
- [ ] Add `missing_worktree_unknown` fixture.
- [ ] Run `python3 evals/check_learning_log.py`.
- [ ] Commit: `test: cover project-aware learning log health`.

### Task 2: Add Project State Loader

**Files:**
- Modify: `scripts/check_learning_log_health.py`

- [ ] Implement `resolve_project_state_path(meta: dict) -> Path | None`.
- [ ] Implement `read_project_state(meta: dict) -> dict | None`.
- [ ] Implement `summarize_project_state(state: dict, state_path: Path) -> dict`.
- [ ] Include task counts, current task, current phase, lifecycle outcome, context health status, and next action.
- [ ] Run `python3 evals/check_learning_log.py` and verify the new active fixture still fails until classification changes.
- [ ] Commit: `feat: read project state in learning log health`.

### Task 3: Replace PID-Centered Stale Logic

**Files:**
- Modify: `scripts/check_learning_log_health.py`
- Modify: `references/learning-log.md`
- Modify: `docs/state-and-logging.md`

- [ ] Keep helper pid in output only as metadata.
- [ ] Remove helper pid liveness from direct stale classification.
- [ ] Add classification precedence: final, project state, stale candidate, unknown.
- [ ] Return `diagnostics.info` for append-only index mismatch.
- [ ] Return `diagnostics.warnings` for actionable issues.
- [ ] Run `python3 scripts/check_learning_log_health.py --latest 3 --json`.
- [ ] Commit: `fix: avoid false stale learning run reports`.

### Task 4: Add Git State Drift Summary

**Files:**
- Modify: `scripts/check_learning_log_health.py`
- Modify: `evals/check_learning_log.py`

- [ ] Implement a small `git status --short --untracked-files=all` reader guarded by worktree existence.
- [ ] Count modified, deleted, staged, and untracked entries.
- [ ] Include branch and short head when git commands succeed.
- [ ] Emit `dirty_worktree_during_in_progress` only when status count is nonzero and state is active.
- [ ] Do not fail the reporter when git is unavailable or the path is not a worktree.
- [ ] Commit: `feat: summarize git drift in run health`.

### Task 5: Tighten Context Health Timestamp Rules

**Files:**
- Modify: `references/execution-cycle.md`
- Modify: `references/state-schema.md`
- Modify: `scripts/validate_state.py`
- Modify: `evals/check_state_schema.py`

- [ ] Document that `context_health.last_checked_at` must be updated whenever `context_health` changes.
- [ ] Add validation for terminal states: if `lifecycle_outcome=finished`, `context_health.last_checked_at` must be present and not older than `timestamps.updated_at`.
- [ ] Keep active-run validation advisory or non-blocking unless a terminal outcome is claimed.
- [ ] Add a fixture proving stale context-health timestamps fail only for finished state.
- [ ] Commit: `fix: validate terminal context health freshness`.

### Task 6: Update Docs And Verification Log

**Files:**
- Modify: `references/learning-log.md`
- Modify: `docs/state-and-logging.md`
- Modify: `docs/evals-and-verification.md`
- Modify: `docs/risks-limitations-deferrals.md`
- Modify: `docs/verification-log.md`

- [ ] Document final/project-state/index precedence.
- [ ] Document helper pid limitations.
- [ ] Document new status values and diagnostics.
- [ ] Record verification commands and skipped checks.
- [ ] Run package checks listed in `references/change-protocol.md`.
- [ ] Commit: `docs: document project-aware run health reporting`.

## Verification Matrix

Run these before claiming completion:

```bash
python3 evals/check_learning_log.py
python3 evals/check_state_schema.py
python3 evals/check_skill_contract.py --skill SKILL.md
python3 scripts/check_learning_log_health.py --latest 5 --json
python3 /Users/kws/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
git diff --check -- skills/kws-codex-plan-executor
graphify update .
```

If `graphify update .` changes generated files, include those changes with the implementation branch.

## Residual Risks

- A state-aware reporter still cannot prove a Codex session is actively running; it can only report whether persisted state looks active, terminal, stale, or inconsistent.
- A clean worktree with an old active state may still be ambiguous; classify it as `stale_candidate`, not `stale`.
- Worktrees can be moved or deleted after logs are written. Missing state should be a diagnostic, not a crash.
