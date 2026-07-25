---
name: kws-codex-plan-executor
description: Use when approved Superpowers implementation plans must run in fixed order and survive process interruption.
metadata:
  version: "2.1.1"
  updated_at: "2026-07-24"
---

# KWS Codex Plan Executor

Release metadata remains at 2.1.1 until the Task 7 publication rewrite. The
active cutover runtime is a thin local durability boundary for one
caller-supplied Superpowers execution contract. For bounded work that does not
need a durable run, use a direct Superpowers launch in the current worktree.

## Ownership And Launch Boundary

CPE maintains one execution environment and verifies submitted facts.
Superpowers decides what work and verification are correct.

CPE snapshots the submitted documents, creates one reused isolated worktree, and
launches Codex directly into Superpowers in that worktree. The launcher passes
paths and current Git facts, but does not compile a plan or choose a task,
review, fix, test, subagent, commit, or release workflow. Resume uses the same
worktree and immutable document bundle.

```bash
python3 scripts/cpe.py run \
  --document /abs/design.md --document /abs/implementation.md \
  --workspace /abs/repository \
  --superpowers-skill subagent-driven-development
python3 scripts/cpe.py resume --run-id RUN_ID
python3 scripts/cpe.py inspect --run-id RUN_ID
```

The active CPE commands are exactly `run`, `resume`, and `inspect`.
`run` defaults to `workspace-write`.
`danger-full-access` is an explicit immutable run-creation opt-in.

The accepted `danger-full-access` residual risk is that writes outside the
worktree are not fully observable or reversible; prompt and remote prohibitions
plus Git gates remain, but are not a sandbox substitute. The child prompt also
prohibits merge, push, deploy, and writes outside its worktree; that is a guard,
not proof of complete containment.

## Controller-Owned Completion And Resume

Superpowers owns engineering completion; CPE only reports a mechanical
`handed_off`, `failed`, `blocked`, or `interrupted` status.
CPE has no public retry, recovery, or verification command.

`resume --run-id RUN_ID` uses the saved controller session first. Only an
explicit saved-session-unavailable result permits one fresh controller
fallback. `inspect` is read-only, including for recognized legacy state.
CPE never selects product verification or claims merge, push, deployment,
publication, or product acceptance.

## Local Installation And Verification

The tracked `skills/kws-codex-plan-executor/` directory is the source of truth.
Install it for Codex and Claude Code with symlinks from `skills/README.md`; do
not copy this skill into either tool directory and do not edit Superpowers
upstream.

For a behavior change, add a focused deterministic eval first. The complete
local gate is `./evals/run.sh`; use it only at the final clean revision after
the externally owned integration review. During a change, run the focused test
and applicable static checks. Evals are sequential, network-free,
credential-free, and model-free.
