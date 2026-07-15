---
name: kws-codex-plan-executor
description: Execute one or more approved Superpowers implementation plans sequentially in one durable isolated worktree.
metadata:
  version: "1.2.0"
  updated_at: "2026-07-15"
---

# KWS Codex Plan Executor

Use CPE when approved Superpowers implementation plans must run in a fixed
order and survive process interruption. For bounded same-session work, use the
plan's Superpowers workflow directly.

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

CPE launches one fresh plan controller per plan. Superpowers owns task
execution, review, fixes, the cross-task final review, final verification, and
commits inside that session. CPE owns snapshots, the worktree, process launch,
plan checkpoints, bounded recovery, resume, inspection, and mechanical result
acceptance; it does not become a task mapper or product-quality role.

The controller uses file-backed task briefs, reports, review packages, review
files, and the progress ledger. Only compact status, commit, test, finding, and
next-action returns stay in controller context. Task workers run focused
verification, reviewers reuse recorded evidence, and full verification runs
once at the final HEAD. A completed output requires the exact clean worktree
HEAD, successful verification, and a valid workflow receipt.

Automatic recovery is conditional and bounded: one private recovery capsule
may drive one fresh attempt after interruption, timeout, or a structured
retryable failure with a changed strategy. Blocked, non-retryable, integrity,
and repeated-signature outcomes stop. An explicit `--retry-failed` grants one
operator-initiated attempt.

The existing attempt-finished event may record aggregate usage totals from the
Codex session. Those totals can include the root controller and subagents and
are not claimed as a root-versus-subagent split.

## Operational Safety

Only one mutating `run` or `resume` owns a run at a time; a competitor returns
an interrupted `run_busy` result without launching another child. CPE starts
each child in one POSIX process group, cleans the complete group on timeout,
interrupt, or termination, and retains a bounded one-MiB attempt-log tail.

Run creation persists `initializing` before worktree creation. Resume verifies
or recreates only the exact recorded worktree before continuing. Attempt
identity and its private result placeholder are durable before launch. Codex
returns the strict result object as its final response, and accepted results
become read-only evidence.

Run the deterministic gate with `./evals/run.sh`. See [README.md](README.md)
for requirements, state and result contracts, failure meanings, limitations,
and the complete verification commands.
