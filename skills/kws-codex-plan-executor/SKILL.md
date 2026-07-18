---
name: kws-codex-plan-executor
description: Use when approved Superpowers implementation plans must run in fixed order and survive process interruption.
metadata:
  version: "2.0.0"
  updated_at: "2026-07-18"
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

## Thin Audit Boundary

CPE records facts about what Superpowers did; it does not decide what
Superpowers must do. Superpowers remains the sole semantic owner of task
execution, TDD, reviews, finding-fix cycles, final verification, subagent
coordination, and commits. CPE owns ordered immutable inputs, one isolated
worktree, bounded sequential resume, mechanical evidence checks, and read-only
operator reporting. It does not require or reconstruct a task, delta, or
whole-branch review lifecycle, a transition-obligation engine, a fork or
context-reference policy, or cross-run signal promotion.

The verification helper reuses success only within the same-run identity and
the exact eight-part content key: command ID, argv digest, resolved working
directory, `HEAD`, environment fingerprint, phase, input digest, and mutable
input policy. A dirty worktree, changed input digest, changed key field,
nondeterministic command, or always-execute policy forces execution. If the
helper or cache cannot be trusted, the fallback executes once, is recorded as
uncached, and is never reused.

Mechanical completion remains fail closed on `final_review_path`,
`final_review_head`, `open_finding_ids`, `open_obligation_ids`, successful
verification outcomes, exact clean `HEAD`, and ancestry. These checks validate
submitted facts; they do not choose the Superpowers workflow that produced
them.

Optimization reports derive field-complete aggregate usage facts from
authoritative events: input, cached input, paired uncached input, output,
reasoning output, independently known and unknown attempt counts, missing
duration and reason, aggregate controller-and-nested scope, and unavailable
per-agent attribution. Missing values remain unknown, never zero. The read-only
metadata-only produced-artifact inventory reports file and byte pressure; it is
not consumed tokens and never affects acceptance. Declared context remains
unavailable unless directly evidenced.

The completion handoff records branch, observed `HEAD`, last-known `HEAD`, and
`integration=not_observed`; it does not claim merge, push, deploy, publish, or
product acceptance. If a terminal CPE run is followed by manual inline work,
the failed run remains immutable audit-only, `.superpowers/sdd/progress.md` is
the current inline ledger, and the truthful outcome is `inline continuation
verified`, never CPE acceptance.

For this local 2.0 release, `live canary not run` records the current Codex CLI
usage limit. Deterministic sanitized fixtures are local release evidence only;
they are not a canary, publication, or integration claim.

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

Superpowers owns implementation correctness. CPE owns the durable plan
boundary and decides only whether parent-observed evidence justifies another
bounded controller slice. It does not interpret plan prose or prescribe task,
review, fix, or subagent workflow semantics.

## Recovery Contract

- The exit mappings apply only to `run` and `resume`: `completed` is 0,
  `failed` is 1, `blocked` is 2, and `checkpointed` is 3. A successful
  read-only `inspect` exits 0 even when the stored status is `blocked`,
  `failed`, or `checkpointed`.
- A parent-observed unavailable capability is a typed blocker. Resuming with
  the same environment fingerprint launches zero compiler, model, or
  verification children. A changed fingerprint permits a bounded resume.
- A pre-execution worktree creation or reconciliation environment failure is
  durably `blocked` in both run and current-plan state with a typed
  parent-observed, operator-owned reason. Across `run`, `inspect`, and plain
  `resume`, the durable status is `blocked`; this boundary never persists
  `failed` and never requires `--retry-failed`. Repeated failure consumes zero
  plan attempts, controller launches, or recompilation and launches no model
  or verification child. After the environment recovers, plain `resume`
  safely creates or reconciles the worktree and executes with the existing
  compiled index. A missing worktree after plan execution has begun remains a
  fail-closed integrity error.
- The progress fingerprint covers durable `HEAD`, completed task IDs, and the
  current task ID. Review, finding-fix, obligation, and coordination events do
  not drive recovery decisions. A timed-out slice with a changed fingerprint
  is productive and may continue within budget. The first unchanged timeout
  receives at most one confirmation slice; the second consecutive no-progress
  slice stops as stalled.
- The fixed per-plan defaults are a 3600-second controller slice, 6 productive
  progress checkpoints, 21600 seconds of wall time, and 8 controller launches.
  Every budget is checked before another launch.
- `checkpointed` is a durable resumable state, not a failure state.
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

## Project Tool Policy

Graphify is not a project-default tool. Controllers, implementers, and
reviewers do not load its skill, build or refresh a graph, or add Graphify to
verification merely because they are working in a codebase. Use it only when
the approved plan explicitly names Graphify or requires a Graphify artifact.

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
