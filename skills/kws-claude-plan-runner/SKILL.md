---
name: kws-claude-plan-runner
description: Use when approved Superpowers specifications and one or more ordered implementation plans must run autonomously through Claude Code with durable recovery and fail-closed ready-for-integration evidence.
metadata:
  version: "2.0.0"
  updated_at: "2026-07-25"
---

# Claude Plan Runner

## Overview

This thin wrapper gives specifications and plans to Superpowers as immutable
inputs handed unchanged to Superpowers.
Do not merge, rewrite, or positionally pair them. Superpowers owns task
decomposition, SDD dispatch, TDD, task review, fixes, and the final whole-branch
review.

The runner owns exact external facts: immutable input digests, one worktree,
plan order, root recovery actions, ordered plan handoff HEADs, accepted
verification digests and receipts, and the run outcome. It does not mirror
Superpowers task or review state.

## Run

Preinstall uv-managed normal-GIL CPython `>=3.13,<3.14` with
`uv python install 3.13`, then use the self-locating launcher:

```bash
./scripts/runner run \
  --workspace /absolute/repository \
  --spec /absolute/spec-a.md --spec /absolute/spec-b.md \
  --plan /absolute/plan-a.md --plan /absolute/plan-b.md
./scripts/runner inspect --run-id RUN_ID
./scripts/runner resume --run-id RUN_ID
./scripts/runner resume --run-id RUN_ID --retry-blocked
./scripts/runner resume --run-id RUN_ID \
  --retry-failed --strategy-note "new evidence and changed strategy"
```

Every packet includes all immutable specifications and the current plan only;
future plan paths are excluded. Every prior plan handoff HEAD remains an
ancestor of the accepted candidate.

## Claude transport

Initial roots use `claude -p`, `stream-json`, `--verbose`, an
inline JSON schema, and a new UUID through `--session-id`. The one healthy root resume uses
the recorded UUID with `--resume`; implicit selection is forbidden. The
adapter scrubs nested-session markers and unrelated credentials.

The adapter supplies one variadic `--disallowedTools` flag against accidental
remote mutation. It is
not a security boundary against a same-UID process; hard isolation belongs to
Waygent/kernel.

## Recovery and completion

The canonical recovery source is durable state, Git HEAD, ledger, and receipts,
not conversation memory. Every plan starts with a fresh root. A plan gets at
most one healthy same-plan session resume, expressed as one healthy root resume,
and one fresh-root fallback when resume fails or context becomes suspect.

A live controller continues the bounded recovery loop itself in `recovering`;
`resumable` means an external invocation must restart a stopped controller.
Only external authority, provider/runtime unavailability, irreconcilable
requirements, exhausted strategies, or integrity failure stop the run.

Plan status is `pending`, `running`, or `implemented`. Run status carries
`recovering`, `resumable`, and `ready_for_integration`; never assign those
values to a plan. A plan becomes `implemented` only after its Superpowers
ledger and Git handoff are sealed.

The final plan carries all immutable requirements and owns the single final
whole-branch review. The run becomes `ready_for_integration` only after every
plan is implemented and exact verification receipts plus that review succeed
at one unchanged candidate HEAD. The runner executes exact argv without a
shell, enforces each deadline, and seals each receipt. A HEAD change invalidates
verification and review.

A dirty checkpoint records HEAD, branch, porcelain, and bounded content digests
for drift detection. It is not a backup and cannot restore files.

Do not merge, push, or deploy. Every provider packet sets
`integration_policy=keep`; successful handoff records
`integration=not_observed`.

Version 1 state is inspect-only. Version 2 is required for `run`, `resume`, and
recovery; older state is never upgraded or reinterpreted in place.

## Runtime and validation

Active commands never download Python or fall back to system Python.
`./evals/run.sh` is deterministic fake-provider validation; a live Claude
canary is separate explicit evidence.

`run` and `resume` exit 0 only for `ready_for_integration`.
`inspect` exits 0 for any valid, readable run state; it does not assert
completion. `inspect` exits 64 for an unknown run and 65 for invalid state.
Run `./scripts/runner --help` and subcommand `--help` for the full CLI.
