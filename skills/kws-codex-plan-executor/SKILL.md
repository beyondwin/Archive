---
name: kws-codex-plan-executor
description: Execute one or more approved Superpowers implementation plans sequentially in one durable isolated worktree.
metadata:
  version: "2.0.0"
  updated_at: "2026-07-17"
---

# KWS Codex Plan Executor

Use CPE when approved Superpowers implementation plans must run in a fixed
order and survive process interruption. For bounded same-session work, use the
plan's Superpowers workflow directly.

CPE 2.0 uses only format-version-2 run state, child-result, compiled-index, and
optimization-report contracts; it consumes a strict append-only execution
ledger and does not read or migrate format-1 run state. Its recovery controller
is evidence-driven and progress-aware: it avoids relaunches when
parent-observed capabilities are unchanged, permits bounded recovery after the
environment or durable work changes, and can repair only safe artifact-path
spellings without a model turn.

## Commands

```bash
python3 scripts/cpe.py run --spec /abs/spec.md --plan /abs/plan.md --workspace /abs/repo
python3 scripts/cpe.py resume --run-id RUN_ID
python3 scripts/cpe.py resume --run-id RUN_ID --retry-failed
python3 scripts/cpe.py inspect --run-id RUN_ID
```

Repeated plan flags preserve execution order. All specification snapshots are
available to each plan session. Plans share one isolated worktree, and resume
starts at the first incomplete plan without relaunching completed plans.

Superpowers owns implementation correctness: task execution, TDD, review,
finding fixes, cross-task final review, verification, and commits. CPE owns the
durable plan boundary and decides only whether the evidence justifies another
controller slice. It also owns input snapshots, the isolated worktree,
capability probes, budgets, resume, inspection, mechanical result acceptance,
and derived optimization reports. CPE is not a task mapper or a product-quality
judge.

The controller uses file-backed task briefs, reports, review packages, review
files, the strict execution ledger, and the progress ledger. Only compact
status, commit, verification, finding, and next-action returns remain in
controller context. Task workers run focused verification, reviewers reuse
recorded evidence, and the complete gate runs once at the final `HEAD`.

## Recovery Contract

- A parent-observed unavailable capability is a typed blocker. Resuming with
  the same environment fingerprint launches zero compiler, model, or
  verification children. A changed fingerprint permits a bounded resume.
- A pre-execution worktree creation or reconciliation environment failure is
  durably `blocked` in both run and current-plan state with a typed
  parent-observed, operator-owned reason. It consumes zero plan attempts and
  controller launches. `inspect` and plain `resume` agree on `blocked`; plain
  resume safely retries creation without recompiling, and either remains
  blocked with zero compiler, model, or verification launches or recovers and
  executes with the existing compiled index. A missing worktree after plan
  execution began remains a fail-closed integrity error.
- The progress fingerprint covers durable `HEAD`, completed task IDs, current
  task ID, accepted review IDs, and closed finding IDs. A timed-out slice with
  a changed fingerprint is productive and may continue within budget. The first
  unchanged timeout receives at most one confirmation slice; the second
  consecutive no-progress slice stops as stalled.
- The fixed per-plan defaults are a 3600-second controller slice, 6 productive
  progress checkpoints, 21600 seconds of wall time, and 8 controller launches.
  Every budget is checked before another launch.
- `checkpointed` is a durable resumable state and exit 3, not a failure state.
  Child checkpoints remain subject to the same post-slice budgets.
- Safe result-envelope repair changes only absolute workflow-receipt
  `ledger_path` and `final_review_path` spellings into verified worktree-relative
  paths. It preserves the immutable original result and its digest, writes a
  separate repaired receipt, changes no semantic result field, and consumes
  zero model turns, controller launches, or attempts. Unsafe or drifted
  evidence fails closed.

Run artifacts stay outside the repository. With the default Codex home they
live under `~/.codex/orchestrator/<run-id>/`; attempt logs are in
`logs/<plan-id>-attempt-<n>.log`, and derived reports are
`reports/optimization-report.json` and
`reports/optimization-report.md`. The isolated worktree is
`~/.codex/worktrees/<run-id>/`.

## Operational Safety

Only one mutating `run` or `resume` owns a run at a time; a competitor returns
a checkpointed `run_busy` result without launching another child. CPE starts
each child in one POSIX process group, cleans the complete group on timeout,
interrupt, or termination, and retains a bounded one-MiB attempt-log tail.

Run creation persists `preparing` before compilation and worktree execution.
Resume verifies the exact recorded worktree before continuing. Attempt identity
and its private result placeholder are durable before launch. Codex returns the
strict format-2 result object as its final response, and accepted results become
read-only evidence.

The child remains in `workspace-write`; CPE adds only the worktree's exact
resolved Git common directory so normal linked-worktree commits can write their
index, objects, logs, and branch ref.

Run the deterministic integration gate with `./evals/run.sh`. See
[README.md](README.md) for requirements, format-2 state and result contracts,
typed stop meanings, limitations, artifact locations, and all static checks.
