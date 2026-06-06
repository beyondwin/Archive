# F02 — Dogfood: task-complete clobbered `timing.started` (v2.28)

**Date**: 2026-06-07
**Decision**: FIX (shipped in commit `415ec68`)

## How it was found

Dogfooding the **new v2.28 finalize gate against this very orchestration run**.
After all 8 tasks landed, `finalize_run.py --check` on the run's own `state.json`
raised the D003 cost/timing FAIL: every terminal task had `timing.started == null`,
so the gate reported `timing_tracking_absent`. The new gate caught a real defect in
the instrumentation it was built to police — the exact failure mode v2.28 targets.

## Root cause

`scripts/phase_boundary.py`:

- `cmd_task_start` wrote `tasks[task].timing.started = now`.
- `cmd_task_complete` did `timing = result.setdefault("timing", {}); timing["completed"]
  = now; tasks[task] = result` — the `tasks[task] = result` **replaced the whole entry**,
  discarding the `timing.started` that task-start had written.

Consequence: on **every** real orchestrator run `timing.started` was always null at
finalize. The D003 `timing_inverted` check (which compares started vs completed) could
therefore **never fire on a real run** — only on hand-built fixtures — and the finalize
gate raised `timing_tracking_absent` on every honest run. A v2.28 deliverable was dead
on arrival at the recording site.

## Fix (commit `415ec68`, TDD)

In the `cmd_task_complete` mutate closure, preserve a prior `started` unless the result
itself carries an explicit one:

```python
prior_started = ((tasks.get(task) or {}).get("timing") or {}).get("started")
timing = result.setdefault("timing", {})
if prior_started and not timing.get("started"):
    timing["started"] = prior_started
timing["completed"] = ss._utc_now_iso()
tasks[task] = result
```

3 RED→GREEN tests in `test_phase_boundary.py` (started preserved; explicit result-started
wins; no-prior-start is fine, no crash). Also closed the recorded Task-3 `_parse_iso`
residual: 2 tests in `test_finalize_run.py` drive a **mixed aware+naive** timestamp pair
through `timing_inverted` (the path that, pre-normalization, raised
`TypeError: can't compare offset-naive and offset-aware datetimes`) — confirmed real
coverage, no TypeError. Suite 223 → **228** / 0; contract `passed: true`.

## Honest residual on THIS run

The fix preserves `timing.started` for **future** runs. This run's 8 task entries were
written **before** the fix existed, so their `started` is unrecoverable. Resolved
honestly, not hidden: set run-level `timing_tracking_waived=true` with reason
`"timing.started lost to pre-fix task-complete clobber (root-caused + fixed in 415ec68);
agent-dispatch attached run, started unrecoverable for already-completed tasks"`. The
waive demotes the blocking FAIL to per-task `timing_started_missing` WARNs — the loud,
discoverable treatment, never a silent pass. Re-dogfooded `finalize_run.py --fix` →
`passed: true` (only the design-accepted `agentlens_run_absent` / `quality_trend_sparse`
/ `timing_started_missing` WARNs remain).

## Lesson

The v2.28 thesis — *"attack instrumentation at the recording site, not just the finalize
boundary"* — is validated by its own dogfooding: a detect-only gate would have reported
the absence forever; moving the write into the unskippable task-complete path is what
actually makes `timing_inverted` reachable on real runs.
