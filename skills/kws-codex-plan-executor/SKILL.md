---
name: kws-codex-plan-executor
description: Execute one or more approved Superpowers implementation plans sequentially in one durable isolated worktree.
metadata:
  version: "1.0.0"
  updated_at: "2026-07-14"
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

Superpowers owns implementation, TDD, review, fixes, product verification, and
commits inside each fresh plan session. CPE owns snapshots, the worktree,
process launch, plan checkpoints, bounded retry, resume, and inspection.

Each plan gets an initial attempt and one automatic recovery attempt. A failed
plan can receive one additional attempt per explicit `--retry-failed`
invocation. Blocked plans stop the current invocation without automatic retry.

Run the deterministic gate with `./evals/run.sh`. See [README.md](README.md)
for requirements, state and result contracts, failure meanings, limitations,
and the complete verification commands.
